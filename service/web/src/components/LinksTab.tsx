import { useEffect, useMemo, useState } from "react";
import { api, type LinkState, type ObjectLinks } from "../api";
import FindingContextView, { SECTION_SHORT, STAGE_SHORT, STATE_TEXT } from "./FindingContextView";

interface Props {
  processId: string;
  /** Открыть проверку на записи — из «той же проверки» и из списка находок. */
  onOpenFinding: (id: string) => void;
}

const STAGES = ["PD", "RD", "ID"];
const SECTION_ORDER = ["PZ", "GP", "AR", "KR", "EOM", "VK", "OV", "SS", "TX", "PB", "POS", "POD", "OOS", "ODI"];
const ARC: Record<LinkState, { color: string; dash?: string }> = {
  VIOLATION: { color: "var(--hm-violation)" },
  CANDIDATE: { color: "var(--hm-candidate)" },
  CLEAN: { color: "var(--hm-clean)" },
  NOT_COMPARABLE: { color: "var(--pencil)", dash: "2 3" },
  SUSPICION: { color: "var(--pale)", dash: "6 4" },
  MISSING_EVIDENCE: { color: "var(--pale)", dash: "1 3" },
};
const cellKey = (c: { stage: string; section: string }) => `${c.stage}|${c.section}`;
const pairKey = (l: ObjectLinks["links"][number]) => [cellKey(l.from), cellKey(l.to)].sort().join(">");
const STATE_ORDER: LinkState[] = ["VIOLATION", "CANDIDATE", "NOT_COMPARABLE", "MISSING_EVIDENCE", "CLEAN", "SUSPICION"];

/**
 * Вкладка «Связи документов» дашборда (#82, дизайн — docs/design/82-document-links.html).
 * Слева — карта объекта: документы по стадиям и разделам, находки — дугами между клетками,
 * если их доказательства лежат в двух стадиях. Щелчок по дуге оставляет в списке находки
 * этой связи; справа — контекст выбранной находки.
 */
export default function LinksTab({ processId, onOpenFinding }: Props) {
  const [data, setData] = useState<ObjectLinks | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .links(processId)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setPicked(d.findings[0]?.id ?? null);
      })
      .catch((e) => alive && setError((e as Error).message));
    return () => {
      alive = false;
    };
  }, [processId]);

  const sections = useMemo(() => {
    if (!data) return [];
    const present = [...new Set(data.grid.map((g) => g.section))];
    const rank = (s: string) => (s === "OTHER" ? 999 : SECTION_ORDER.indexOf(s) < 0 ? 500 : SECTION_ORDER.indexOf(s));
    return present.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  }, [data]);

  if (error) return <div className="alert">Карта связей не загрузилась: {error}</div>;
  if (!data) return <div className="empty-state">Карта связей собирается…</div>;

  const count = new Map(data.grid.map((g) => [cellKey(g), g.documents]));
  const W = 470, rowH = 30, top = 32, left = 92, colW = (W - left - 8) / 3, cellW = colW - 32;
  const H = top + sections.length * rowH + 10;
  const cx = (s: string) => left + STAGES.indexOf(s) * colW + 6;
  const cy = (sec: string) => top + sections.indexOf(sec) * rowH;
  const chosen = link !== null ? data.links[link] : null;
  // дуга — пара клеток и состояние: щелчок оставляет находки именно этой дуги
  const list = chosen
    ? data.findings.filter(
        (f) =>
          f.state === chosen.state &&
          f.cells.some((c) => cellKey(c) === cellKey(chosen.from)) &&
          f.cells.some((c) => cellKey(c) === cellKey(chosen.to)),
      )
    : data.findings;
  // дуги одной пары клеток с разными состояниями разводятся, чтобы не лечь друг на друга
  const lane = new Map<number, number>();
  const pairs = new Map<string, number[]>();
  data.links.forEach((l, i) => pairs.set(pairKey(l), [...(pairs.get(pairKey(l)) ?? []), i]));
  for (const ids of pairs.values()) {
    ids.sort((a, b) => STATE_ORDER.indexOf(data.links[a].state) - STATE_ORDER.indexOf(data.links[b].state));
    ids.forEach((i, k) => lane.set(i, (k - (ids.length - 1) / 2) * 6));
  }
  // нарушения рисуются последними — поверх остальных дуг
  const drawOrder = [...data.links.keys()].sort(
    (x, y) => STATE_ORDER.indexOf(data.links[y].state) - STATE_ORDER.indexOf(data.links[x].state),
  );
  const shownLink = hover ?? link;
  const tip = shownLink !== null ? data.links[shownLink] : null;

  return (
    <div className="lk-tab">
      <section className="pane">
        <div className="pane-head">
          <h2>Карта объекта</h2>
          <span className="count" title={data.mixed ? "Смешанные комплекты РД и ИД стоят в колонке РД" : undefined}>
            {STAGES.map((s) => `${STAGE_SHORT[s]} ${data.stages[s] ?? 0}`).join(" · ")}
            {data.mixed ? ` · в РД смешанных с ИД ${data.mixed}` : ""}
          </span>
        </div>
        <div className="lk-map-body">
          {sections.length === 0 ? (
            <div className="empty-state">Принятых документов со стадией нет.</div>
          ) : (
            <div className="lk-map-wrap">
              <svg
                className="lk-map"
                viewBox={`0 0 ${W} ${H}`}
                role="img"
                aria-label={`Карта объекта: документы по стадиям и разделам, связей находок между стадиями ${data.links.length}`}
              >
                {STAGES.map((s) => (
                  <text key={s} className="lk-colhead" x={cx(s) + cellW / 2} y={18} textAnchor="middle">
                    {STAGE_SHORT[s]}
                  </text>
                ))}
                {sections.map((sec) => (
                  <g key={sec}>
                    <text className="lk-rowhead" x={left - 10} y={cy(sec) + 18} textAnchor="end">
                      {SECTION_SHORT[sec] ?? sec}
                    </text>
                    {STAGES.map((s) => {
                      const n = count.get(`${s}|${sec}`) ?? 0;
                      const x = cx(s), y = cy(sec) + 4;
                      return n ? (
                        <g key={s}>
                          <rect x={x} y={y} width={cellW} height={rowH - 8} fill="var(--paper-2)" stroke="var(--pencil)" strokeWidth={1} />
                          <rect x={x} y={y} width={Math.min(cellW, 4 + Math.log2(n + 1) * 11)} height={rowH - 8} fill="var(--tint)" />
                          <text className="lk-cnt" x={x + cellW - 6} y={y + 15} textAnchor="end">
                            {n} док.
                          </text>
                        </g>
                      ) : (
                        <rect key={s} x={x} y={y} width={cellW} height={rowH - 8} fill="none" stroke="var(--rule)" strokeDasharray="3 3" />
                      );
                    })}
                  </g>
                ))}
                {drawOrder.map((i) => {
                  const l = data.links[i];
                  const [a, b] = STAGES.indexOf(l.from.stage) <= STAGES.indexOf(l.to.stage) ? [l.from, l.to] : [l.to, l.from];
                  if (!sections.includes(a.section) || !sections.includes(b.section)) return null;
                  const off = lane.get(i) ?? 0;
                  const x1 = cx(a.stage) + cellW, y1 = cy(a.section) + rowH / 2 + off;
                  const x2 = cx(b.stage), y2 = cy(b.section) + rowH / 2 + off;
                  const skip = STAGES.indexOf(b.stage) - STAGES.indexOf(a.stage) > 1;
                  const bend = skip ? -Math.max(40, Math.abs(y2 - y1) * 0.3 + 30) + off * 2 : 0;
                  const mx = (x1 + x2) / 2;
                  const d = `M${x1},${y1} C${mx},${y1 + bend} ${mx},${y2 + bend} ${x2},${y2}`;
                  const style = ARC[l.state] ?? ARC.MISSING_EVIDENCE;
                  const dim = link !== null && link !== i;
                  return (
                    <g key={i}>
                      <path
                        d={d}
                        fill="none"
                        stroke={style.color}
                        strokeDasharray={style.dash}
                        strokeWidth={(1.3 + Math.log2(l.findings + 1) * 1.3).toFixed(1)}
                        opacity={dim ? 0.18 : 1}
                      />
                      <path
                        d={d}
                        className="lk-hit"
                        role="button"
                        tabIndex={0}
                        aria-label={`${SECTION_SHORT[a.section] ?? a.section} ${STAGE_SHORT[a.stage]} — ${SECTION_SHORT[b.section] ?? b.section} ${STAGE_SHORT[b.stage]}: ${STATE_TEXT[l.state]}, находок ${l.findings}`}
                        onMouseEnter={() => setHover(i)}
                        onMouseLeave={() => setHover(null)}
                        onFocus={() => setHover(i)}
                        onBlur={() => setHover(null)}
                        onClick={() => setLink(link === i ? null : i)}
                        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setLink(link === i ? null : i)}
                      />
                    </g>
                  );
                })}
              </svg>
            </div>
          )}
          <div className="lk-legend">
            {(["VIOLATION", "CANDIDATE", "CLEAN", "NOT_COMPARABLE", "SUSPICION"] as LinkState[]).map((s) => (
              <span key={s}>
                <i style={{ borderTopColor: ARC[s].color, borderTopStyle: ARC[s].dash ? "dashed" : "solid" }} />
                {STATE_TEXT[s]}
              </span>
            ))}
            <span>толщина — число находок</span>
          </div>
          <div className="lk-tip" aria-live="polite">
            {tip
              ? `${SECTION_SHORT[tip.from.section] ?? tip.from.section} (${STAGE_SHORT[tip.from.stage]}) ↔ ${
                  SECTION_SHORT[tip.to.section] ?? tip.to.section
                } (${STAGE_SHORT[tip.to.stage]}): ${STATE_TEXT[tip.state]}, находок ${tip.findings}.` +
                (link !== null && hover === null ? " Щелчок по дуге ещё раз снимает отбор." : "")
              : "Наведите на дугу — появятся разделы, стадии и число находок. Щелчок оставляет в списке находки этой связи."}
          </div>

          <div className="lk-h">
            Находки, связывающие стадии · {list.length}
            {chosen && (
              <button type="button" className="link" onClick={() => setLink(null)}>
                все
              </button>
            )}
          </div>
          <div className="lk-list" role="listbox" aria-label="Находки, связывающие стадии">
            {list.length === 0 && <div className="muted small">Находок с доказательствами в двух стадиях нет.</div>}
            {list.map((f) => (
              <button
                key={f.id}
                type="button"
                role="option"
                aria-selected={f.id === picked}
                className="lk-item"
                onClick={() => setPicked(f.id)}
              >
                <span className={`lk-dot st-${f.state}`} aria-hidden="true" />
                <span className="code">{f.code}</span>
                <span className="lk-item-loc">{f.location ?? f.title ?? "—"}</span>
                <span className="mono small muted">{f.stages.map((s) => STAGE_SHORT[s]).join("·")}</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="pane">
        <div className="pane-head">
          <h2>Контекст находки</h2>
          {picked && (
            <button type="button" className="link count" onClick={() => onOpenFinding(picked)}>
              открыть в проверке
            </button>
          )}
        </div>
        <div className="lk-ctx-body">
          {picked ? (
            <FindingContextView processId={processId} findingId={picked} onOpenFinding={onOpenFinding} />
          ) : (
            <div className="empty-state">Выберите находку слева.</div>
          )}
        </div>
      </section>
    </div>
  );
}
