import { useEffect, useRef, useState, type PointerEvent } from "react";
import { openInTab, sourceUrl, type Evidence } from "../api";
import type { Box } from "../cloud";
import { highlightNote, STAGE, STAGE_NAME } from "../labels";
import { PlanView, usePlan } from "./PageCard";

interface Props {
  processId: string;
  title: string;
  /** Страницы-доказательства проектной стадии и рабочей (или исполнительной). */
  pd: Evidence[];
  rd: Evidence[];
  onClose: () => void;
  /**
   * Подписи сторон вместо «ПД» и «РД»: сравнение двух редакций одного листа (#81) — «изм. 1»
   * и «изм. 3». Левая сторона — `pd`, правая — `rd`.
   */
  labels?: { pd: string; rd: string };
  /** Строка под заголовком: что изменилось на листе и отмечено ли изменение (#81). */
  note?: string | null;
  /** Значения стадий записи: у каждой стороны — значение стадии показанной страницы. */
  values?: Partial<Record<"PD" | "RD" | "ID", string | null>>;
  /** Куда сказать, что исходный файл не открылся. */
  onError?: (message: string) => void;
  /**
   * С какой страницы открывать стороны и куда сообщать о листании (п. 13): сопоставление
   * открывается на той странице, что в карточке, а после закрытия карточка стоит там же.
   */
  index?: { pd?: number; rd?: number };
  onIndex?: (side: "pd" | "rd", index: number) => void;
}

/**
 * Одна сторона сравнения: своя страница, свой масштаб, своя листалка. Масштаб у сторон
 * раздельный намеренно — листы ПД и РД бывают разного формата, и общий масштаб делает
 * один из них нечитаемым.
 */
function Side({
  processId,
  items,
  stage,
  name,
  values,
  onError,
  start,
  onIndex,
}: {
  processId: string;
  items: Evidence[];
  stage: "PD" | "RD";
  name?: string;
  values?: Partial<Record<"PD" | "RD" | "ID", string | null>>;
  onError?: (message: string) => void;
  start?: number;
  onIndex?: (index: number) => void;
}) {
  // открываемся на странице из карточки, иначе — где место обведено (#50)
  const marked = Math.max(items.findIndex((e) => e.highlights?.length), 0);
  const [index, setOwnIndex] = useState(start !== undefined && start < items.length ? start : marked);
  const setIndex = (i: number) => {
    setOwnIndex(i);
    onIndex?.(i);
  };
  const evidence = items[Math.min(index, items.length - 1)];
  const plan = usePlan(processId, evidence);
  const { image, fragment } = plan;
  const [view, setView] = useState<Box | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; view: Box } | null>(null);

  const ready = image.state === "ready";
  const pageW = ready ? image.w : 0;
  const pageH = ready ? image.h : 0;
  const whole: Box | null = ready ? { x: 0, y: 0, w: pageW, h: pageH } : null;

  // при переходе на другую страницу масштаб начинается заново, с фрагмента у облака
  useEffect(() => setView(null), [evidence?.file_id, evidence?.pdf_page_number]);
  useEffect(() => {
    if (ready && !view) setView(fragment ?? { x: 0, y: 0, w: pageW, h: pageH });
  }, [ready, view, fragment, pageW, pageH]);

  const zoomBy = (factor: number, clientX?: number, clientY?: number) => {
    setView((v) => {
      if (!v || !pageW) return v;
      const long = Math.max(pageW, pageH);
      const k = Math.min(Math.max(factor, (long * 0.02) / v.w), (long * 1.5) / v.w);
      let px = v.x + v.w / 2;
      let py = v.y + v.h / 2;
      const ctm = svgRef.current?.getScreenCTM();
      if (ctm && clientX !== undefined && clientY !== undefined) {
        const p = new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse());
        px = p.x;
        py = p.y;
      }
      return { x: px - (px - v.x) * k, y: py - (py - v.y) * k, w: v.w * k, h: v.h * k };
    });
  };

  // колесо слушается напрямую: обработчик React пассивный и не остановит прокрутку страницы
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomBy(Math.exp(e.deltaY * 0.0015), e.clientX, e.clientY);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!view) return;
    drag.current = { x: e.clientX, y: e.clientY, view };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    const ctm = svgRef.current?.getScreenCTM();
    if (!start || !ctm) return;
    setView({
      ...start.view,
      x: start.view.x - (e.clientX - start.x) / ctm.a,
      y: start.view.y - (e.clientY - start.y) / ctm.d,
    });
  };

  const percent = view && pageW ? Math.round(100 * Math.max(pageW / view.w, pageH / view.h)) : 100;
  // картинки нет, а сверять по цитате нечего (страница редакции для сравнения #81): открыть сам файл
  const missing = evidence.quote ? undefined : (
    <span>
      Картинки этой страницы нет.{" "}
      <button
        type="button"
        className="link"
        onClick={() =>
          openInTab(sourceUrl(processId, evidence.file_id), `#page=${evidence.pdf_page_number}`).catch((e) =>
            onError?.(`Исходный файл не открылся: ${(e as Error).message}`),
          )
        }
      >
        Открыть файл на стр. {evidence.pdf_page_number}
      </button>
    </span>
  );
  const label = `${name ?? STAGE_NAME[evidence.stage] ?? STAGE_NAME[stage]}, страница ${evidence.pdf_page_number}`;
  const side = evidence.stage as "PD" | "RD" | "ID";
  const value = values && side in values ? values[side] ?? null : undefined;

  return (
    <section className="compare-side">
      <div className="viewer-head">
        <span className="stage">{name ?? STAGE[evidence.stage] ?? evidence.stage}</span>
        <span className="mono">
          {evidence.file_id} · стр. {evidence.pdf_page_number}
          {evidence.page_count ? `/${evidence.page_count}` : ""}
          {evidence.document_sheet_number != null ? ` · лист ${evidence.document_sheet_number}` : ""}
        </span>
        <span className="legend">{highlightNote(evidence)}</span>
        <div className="viewer-tools">
          {items.length > 1 && (
            <span className="pager">
              <button type="button" aria-label="Предыдущая страница" disabled={index === 0} onClick={() => setIndex(index - 1)}>
                ‹
              </button>
              {index + 1} из {items.length}
              <button
                type="button"
                aria-label="Следующая страница"
                disabled={index >= items.length - 1}
                onClick={() => setIndex(index + 1)}
              >
                ›
              </button>
            </span>
          )}
          <button type="button" className="btn" disabled={!view} onClick={() => zoomBy(1.25)} aria-label="Уменьшить">
            −
          </button>
          <span className="mono zoom-level">{percent}%</span>
          <button type="button" className="btn" disabled={!view} onClick={() => zoomBy(1 / 1.25)} aria-label="Увеличить">
            +
          </button>
          {fragment && (
            <button type="button" className="btn" onClick={() => setView(fragment)}>
              К зоне
            </button>
          )}
          <button type="button" className="btn" disabled={!whole} onClick={() => whole && setView(whole)}>
            Весь лист
          </button>
        </div>
      </div>
      {(value !== undefined || evidence.quote) && (
        <div className="viewer-quote">
          {value !== undefined && <b className="viewer-value">{value ?? "значение не найдено"}</b>}
          {value !== undefined && evidence.quote ? " · " : ""}
          {evidence.quote && `«${evidence.quote}»`}
        </div>
      )}
      <div
        ref={stageRef}
        className="viewer-stage"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
      >
        <PlanView plan={plan} view={view} label={label} svgRef={svgRef} missing={missing} />
      </div>
    </section>
  );
}

/**
 * Сопоставление двух листов во весь экран (#74, по итогам репетиции #53). В правой колонке
 * экрана страницы видны целиком, но штампы, спецификации и подписи на них не читаются, и
 * инспектор уходил открывать исходный PDF. Здесь оба листа рядом, каждый со своим масштабом
 * и панорамированием, облака доказательств остаются на месте.
 */
export default function CompareViewer({ processId, title, pd, rd, onClose, labels, note, values, onError, index, onIndex }: Props) {
  const [split, setSplit] = useState<"columns" | "rows">("columns");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => closeRef.current?.focus(), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const empty = (stage: "PD" | "RD") => (
    <section className="compare-side">
      <div className="viewer-head">
        <span className="stage">{labels ? (stage === "PD" ? labels.pd : labels.rd) : STAGE[stage]}</span>
        <span className="legend">{labels ? "страницы в этой редакции нет" : "страниц этой стадии у записи нет"}</span>
      </div>
      <div className="viewer-stage">
        <div className="plan plan-absent hatched">
          <span>
            {labels
              ? stage === "PD"
                ? "Страница добавлена в новой редакции"
                : "Страница удалена в новой редакции"
              : stage === "PD"
                ? "Страница проекта не найдена"
                : "Страница рабочей документации не найдена"}
          </span>
        </div>
      </div>
    </section>
  );

  return (
    <div className="viewer compare" role="dialog" aria-modal="true" aria-label={`Сопоставление листов: ${title}`}>
      <div className="viewer-head">
        <span className="viewer-title">{title}</span>
        <div className="viewer-tools">
          <button type="button" className="btn" onClick={() => setSplit(split === "columns" ? "rows" : "columns")}>
            {split === "columns" ? "Сверху и снизу" : "Рядом"}
          </button>
          <button ref={closeRef} type="button" className="btn" onClick={onClose} title="Esc">
            Закрыть
          </button>
        </div>
      </div>
      {note && <div className="viewer-quote">{note}</div>}
      <div className={`compare-body compare-${split}`}>
        {pd.length ? (
          <Side
            processId={processId}
            items={pd}
            stage="PD"
            name={labels?.pd}
            values={values}
            onError={onError}
            start={index?.pd}
            onIndex={onIndex && ((i) => onIndex("pd", i))}
          />
        ) : (
          empty("PD")
        )}
        {rd.length ? (
          <Side
            processId={processId}
            items={rd}
            stage="RD"
            name={labels?.rd}
            values={values}
            onError={onError}
            start={index?.rd}
            onIndex={onIndex && ((i) => onIndex("rd", i))}
          />
        ) : (
          empty("RD")
        )}
      </div>
    </div>
  );
}
