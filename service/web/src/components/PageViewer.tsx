import { useEffect, useRef, useState, type PointerEvent } from "react";
import type { Evidence } from "../api";
import type { Box } from "../cloud";
import { highlightNote, STAGE } from "../labels";
import { PlanView, usePlan } from "./PageCard";

interface Props {
  processId: string;
  evidence: Evidence;
  title: string;
  /** Значение стороны, которое сверяется на этой странице: во весь экран оно должно быть видно рядом с цитатой. */
  value?: string | null;
  onClose: () => void;
  /**
   * Листалка по страницам той же стороны (п. 13): инспектор сверяет соседние страницы-доказательства,
   * не закрывая окна. Листание сдвигает и карточку страниц на экране проверки.
   */
  pager?: { index: number; total: number; onIndex: (index: number) => void };
}

/**
 * Страница крупно. Открывается на фрагменте с облаками; колесо масштабирует вокруг указателя,
 * перетаскивание сдвигает, «Весь лист» и клавиша 0 показывают страницу целиком, Esc закрывает.
 * Масштаб меняет viewBox, а не CSS-трансформацию: браузер заново растрирует страницу,
 * и облака остаются тонкими при любом увеличении.
 */
export default function PageViewer({ processId, evidence, title, value, onClose, pager }: Props) {
  const plan = usePlan(processId, evidence);
  const { image, fragment } = plan;
  const [view, setView] = useState<Box | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const drag = useRef<{ x: number; y: number; view: Box } | null>(null);

  const ready = image.state === "ready";
  const pageW = ready ? image.w : 0;
  const pageH = ready ? image.h : 0;
  const whole: Box | null = ready ? { x: 0, y: 0, w: pageW, h: pageH } : null;

  // другая страница — масштаб заново, с фрагмента у облака
  useEffect(() => setView(null), [evidence.file_id, evidence.pdf_page_number]);
  useEffect(() => {
    if (ready && !view) setView(fragment ?? { x: 0, y: 0, w: pageW, h: pageH });
  }, [ready, view, fragment, pageW, pageH]);
  const turn = (step: number) => {
    if (!pager) return;
    const next = pager.index + step;
    if (next >= 0 && next < pager.total) pager.onIndex(next);
  };

  // масштаб вокруг точки экрана; без точки — вокруг центра видимой области
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

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "+" || e.key === "=") zoomBy(1 / 1.25);
      else if (e.key === "-") zoomBy(1.25);
      else if (e.key === "0" && whole) setView(whole);
      else if ((e.key === "f" || e.key === "а") && fragment) setView(fragment);
      else if (e.key === "ArrowLeft") turn(-1);
      else if (e.key === "ArrowRight") turn(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // колесо слушается напрямую: обработчик React пассивный и не может остановить прокрутку листа под окном
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomBy(Math.exp(e.deltaY * 0.0015), e.clientX, e.clientY);
    };
    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
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
    setView({ ...start.view, x: start.view.x - (e.clientX - start.x) / ctm.a, y: start.view.y - (e.clientY - start.y) / ctm.d });
  };

  const percent = view && pageW ? Math.round((100 * Math.max(pageW / view.w, pageH / view.h))) : 100;

  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label={title}>
      <div className="viewer-head">
        <span className="stage">{STAGE[evidence.stage] ?? evidence.stage}</span>
        <span className="mono">
          {evidence.file_id} · стр. {evidence.pdf_page_number}
          {evidence.page_count ? `/${evidence.page_count}` : ""}
          {evidence.document_sheet_number != null ? ` · лист ${evidence.document_sheet_number}` : ""}
          {evidence.document_code ? ` · ${evidence.document_code}` : ""}
        </span>
        <span className="viewer-title">{title}</span>
        <span className="legend">{highlightNote(evidence)}</span>
        <div className="viewer-tools">
          {pager && pager.total > 1 && (
            <span className="pager">
              <button type="button" aria-label="Предыдущая страница" title="Клавиша ←" disabled={pager.index === 0} onClick={() => turn(-1)}>
                ‹
              </button>
              {pager.index + 1} из {pager.total}
              <button
                type="button"
                aria-label="Следующая страница"
                title="Клавиша →"
                disabled={pager.index >= pager.total - 1}
                onClick={() => turn(1)}
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
            <button type="button" className="btn" onClick={() => setView(fragment)} title="Клавиша F">
              К облаку
            </button>
          )}
          <button type="button" className="btn" disabled={!whole} onClick={() => whole && setView(whole)} title="Клавиша 0">
            Весь лист
          </button>
          <button ref={closeRef} type="button" className="btn" onClick={onClose} title="Esc">
            Закрыть
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
        <PlanView plan={plan} view={view} label={title} svgRef={svgRef} />
      </div>
    </div>
  );
}
